package vn.unit.affordability.financial.dto;

import jakarta.validation.constraints.DecimalMin;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

import java.math.BigDecimal;

@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class CreateObligationRequest {

    @NotBlank
    private String dossierId;

    @NotBlank
    @Size(max = 255)
    private String institutionName;

    @NotBlank
    @Size(max = 32)
    private String obligationType;

    @NotNull
    @DecimalMin(value = "0")
    private BigDecimal monthlyPayment;

    @NotNull
    @DecimalMin(value = "0")
    private BigDecimal totalBalance;

    @Min(0)
    private Integer remainingTenorMonths;

    @DecimalMin(value = "0")
    private BigDecimal interestRate;

    @NotBlank
    private String source;

    private Boolean isDuplicated;

    private Boolean isIncludedInDti;

    @Size(max = 500)
    private String notes;
}
