package vn.unit.affordability.shared.config;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.reactive.function.client.WebClient;

@Configuration
public class WebClientConfig {

    @Bean
    public WebClient aiServiceWebClient(AppProperties appProperties, WebClient.Builder builder) {
        return builder
                .baseUrl(appProperties.getAiService().getBaseUrl())
                .build();
    }
}

