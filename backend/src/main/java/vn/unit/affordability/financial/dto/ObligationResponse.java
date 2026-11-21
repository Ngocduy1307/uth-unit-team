package vn.unit.affordability.financial.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

import java.math.BigDecimal;
import java.time.OffsetDateTime;

@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
@Builder
@JsonInclude(JsonInclude.Include.NON_NULL)
public class ObligationResponse {

    private String id;
    private String dossierId;
    private String institutionName;
    private String obligationType;
    private BigDecimal monthlyPayment;
    private BigDecimal totalBalance;
    private Integer remainingTenorMonths;
    private BigDecimal interestRate;
    private String source;
    private Boolean isDuplicated;
    private Boolean isIncludedInDti;
    private String notes;
    private OffsetDateTime createdAt;
}
