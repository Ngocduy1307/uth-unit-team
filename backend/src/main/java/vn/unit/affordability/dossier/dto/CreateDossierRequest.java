package vn.unit.affordability.dossier.dto;

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
public class CreateDossierRequest {

    @NotBlank
    @Size(max = 64)
    private String applicationId;

    @NotBlank
    @Size(max = 64)
    private String applicantId;

    @NotBlank
    @Size(max = 255)
    private String applicantName;

    @NotBlank
    @Size(max = 32)
    private String bankCode;

    @NotBlank
    @Size(max = 64)
    private String makerId;

    @Size(max = 64)
    private String loanProduct;

    @NotNull
    @DecimalMin(value = "1000000")
    private BigDecimal requestedAmount;

    @NotNull
    @Min(value = 1)
    private Integer requestedTenorMonths;

    @NotNull
    @DecimalMin(value = "0.01")
    private BigDecimal proposedInterestRate;

    @NotNull
    @DecimalMin(value = "0")
    private BigDecimal monthlyDeclaredLivingExpense;
}
